       subroutine get_uepath_lov(j,i,iselect,currenttime)

       use muc_mod
       use vector_mod

      integer j,i,iselect,timeindex,ih,ipick,Index1D,ihh,ifrom,ito
      real currenttime,valso,uniform,value
      integer jn,mark2,k1,k2,h1,h2,badih,newih,k,mark
      integer::jpath_tmp(1000)=0
      integer::pathnew2(1000)=0	

       timeindex = 0
       ipick=0
	   jn=0
	   mark=0
c       if(iselect.eq.0) then
c	  ih = 0
c	  icurrnt(j) = 1
c	 else
	  ih = iselect - 1 ! iselect is icurrent
c	 endif

!       ifrom = idnod(i)
       ifrom = jorigin(j)

       ito = MasterDest(jdest(j))
       timeindex = ifix((currenttime/tii)/tad)+1 

!       call DYNA_random_number(uniform,6)


!       do np = 1, NumUepath_lov(ifrom,ito,timeindex)
!        if(ueaccuprob_lov(ifrom,ito,timeindex,np).ge.uniform) exit
!       enddo
!	 ipick = np 
	 ipick = jipick(j)	

!       traverse=>MucPath_lov(ifrom,ito,
!     +           uepath_lov(ifrom,ito,timeindex,ipick))
!
!       do while (associated(traverse%next_node))
!        ih = ih + 1 
!        Index1D = ih
!        value = float(traverse%node)
!        call VhcAtt_Insert(j,Index1D,1,value)
!        traverse=>traverse%next_node
!       enddo

	do ihh =1,MucPathAtt_Lov(ifrom,ito, 
     +           uepath_Lov(ifrom,ito,timeindex,ipick))%node_number

	  value= MUCPath_Lov_Array(ifrom,ito,
     +           uepath_Lov(ifrom,ito,timeindex,ipick))%P(ihh)
		

! skip the centroid of the connector, skip the upstream node of generation link

	  if(ihh.gt.2) then

		ih = ih +1
        Index1D = ih
			jn=jn+1
			
            jpath_tmp(jn)=nint(value)		
        endif   

       enddo
! End of modification


c --   Delete cycling . . . --------------------------------------------
c --
            badih=1
            newih=0
            pathnew2(:)=0
            ih=jn
            h2=1
            mark2=0

            do h1=badih,ih-1
               if(h1.eq.badih)then
                  k1=h1
               elseif(h1.ne.badih.and.mark.eq.1)then
                  k1=h2
               else
                  k1=k1+1
               endif
               mark=0
               do k2=k1+1,ih
                 if(jpath_tmp(k1).eq.jpath_tmp(k2))then
                  mark=1
                  h2=k2
                 endif
               enddo
               if(mark.eq.0)then
                  newih=newih+1
                  pathnew2(newih)=jpath_tmp(k1)
                  if(k1.ge.ih) mark2=1
               endif
               if(k1.ge.ih-1) exit
            enddo

            if(mark2.ne.1)then
		       newih=newih+1
		       pathnew2(newih)=jpath_tmp(ih)
            endif

            badih=1

c            if(iselect.ne.0) badih=icurrnt(j)

            do k1=badih,badih+newih-1
                jpath_tmp(k1)=pathnew2(k1-badih+1)
            enddo

c			jpath_tmp(k)=destination(jdest(j))
c			nnpath(j)=k
c ---------------------------------------------------------------------------

      ih=iselect-1
      if(jn.gt.0.and.newih.gt.0)then
c	  ih=ih+1
        do k=1,newih
	      ih=ih+1
          Index1D=ih
          valso=float(jpath_tmp(k))	
c          if(j.eq.55) print *, valso,Index1D,jpath_tmp(k)
          call VhcAtt_Insert(j,Index1D,1,valso)
        enddo 
      endif
	  
       nnpath(j)=ih
	   
       call VhcAtt_Clear(j,ih+1)

       return
       end

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


       subroutine get_genelink_from_uepath_lov(j,igenelink)

       use muc_mod
	 use vector_mod

       integer j,igenelink,timeindex
       real uniform 

       timeindex = 0

       ifrom = jorigin(j)
       ito = MasterDest(jdest(j))
       timeindex = ifix((stime(j)/tii)/tad)+1 
       call DYNA_random_number(uniform,6)


       do np = 1, NumUepath_lov(ifrom,ito,timeindex)
        if(ueaccuprob_lov(ifrom,ito,timeindex,np).ge.uniform) exit
       enddo
	 jipick(j) = np 

	
	isize= MucPathAtt_lov(ifrom,ito,
     +           uepath_Lov(ifrom,ito,timeindex,jipick(j)))%node_number

	  iupstreamnode= MUCPath_Lov_Array(ifrom,ito,
     +           uepath_Lov(ifrom,ito,timeindex,jipick(j)))%P(2)

	  idownstreamnode= MUCPath_Lov_Array(ifrom,ito,
     +           uepath_Lov(ifrom,ito,timeindex,jipick(j)))%P(3)


	  igenelink = GetFLinkFromNode(iupstreamnode,idownstreamnode)

       return
       end




