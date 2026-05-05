       subroutine get_uepath_hov(j,i,iselect,currenttime)

       use muc_mod
	 use vector_mod

       integer j,i,iselect,timeindex,ih,ipick
       real currenttime,uniform 
       integer Index1D
	 real value

     

       timeindex = 0
       ipick=0

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


!       do np = 1, NumUepath_hov(ifrom,ito,timeindex)
!        if(ueaccuprob_hov(ifrom,ito,timeindex,np).ge.uniform) exit
!       enddo
!	 ipick = np 
	 ipick = jipick(j)	

!       traverse=>MucPath_hov(ifrom,ito,
!     +           uepath_hov(ifrom,ito,timeindex,ipick))
!
!       do while (associated(traverse%next_node))
!        ih = ih + 1 
!        Index1D = ih
!        value = float(traverse%node)
!        call VhcAtt_Insert(j,Index1D,1,value)
!        traverse=>traverse%next_node
!       enddo




	do ihh =1,MucPathAtt_Hov(ifrom,ito, 
     +           uepath_Hov(ifrom,ito,timeindex,ipick))%node_number

	  value= MUCPath_Hov_Array(ifrom,ito,
     +           uepath_Hov(ifrom,ito,timeindex,ipick))%P(ihh)
		

! skip the centroid of the connector, skip the upstream node of generation link

	  if(ihh.gt.2) then

		ih = ih +1
        Index1D = ih
	  call VhcAtt_Insert(j,Index1D,1,value)
        endif   

       enddo
! End of modification

       nnpath(j) = ih 
	 call VhcAtt_Clear(j,ih+1)

       return
       end

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


       subroutine get_genelink_from_uepath_hov(j,igenelink)

       use muc_mod
	 use vector_mod

       integer j,igenelink,timeindex
       real uniform 
       

     

       timeindex = 0

       ifrom = jorigin(j)
       ito = MasterDest(jdest(j))
       timeindex = ifix((stime(j)/tii)/tad)+1 
       call DYNA_random_number(uniform,6)


       do np = 1, NumUepath_hov(ifrom,ito,timeindex)
        if(ueaccuprob_hov(ifrom,ito,timeindex,np).ge.uniform) exit
       enddo
	 jipick(j) = np 

	
	isize= MucPathAtt_hov(ifrom,ito,
     +           uepath_Hov(ifrom,ito,timeindex,jipick(j)))%node_number

	  iupstreamnode= MUCPath_Hov_Array(ifrom,ito,
     +           uepath_Hov(ifrom,ito,timeindex,jipick(j)))%P(2)

	  idownstreamnode= MUCPath_Hov_Array(ifrom,ito,
     +           uepath_Hov(ifrom,ito,timeindex,jipick(j)))%P(3)


	  igenelink = GetFLinkFromNode(iupstreamnode,idownstreamnode)

       return
       end




