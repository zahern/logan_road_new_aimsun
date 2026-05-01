       subroutine get_sopath_lov(j,i,iselect,currenttime)

       use muc_mod
	 use vector_mod

       integer j,i,iselect,timeindex,ih,ipick
       real currenttime,uniform 
       integer Index1D
	 real valso



     

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


!       do np = 1, NumUepath_lov(ifrom,ito,timeindex)
!        if(soaccuprob_lov(ifrom,ito,timeindex,np).ge.uniform) exit
!       enddo
!	 ipick = np 
	 ipick = jipick(j)	

!       traverse=>MucPath_lov(ifrom,ito,
!     +           sopath_lov(ifrom,ito,timeindex,ipick))
!
!       do while (associated(traverse%next_node))
!        ih = ih + 1 
!        Index1D = ih
!        valso = float(traverse%node)
!        call VhcAtt_Insert(j,Index1D,1,valso)
!        traverse=>traverse%next_node
!       enddo




	do ihh =1,MucPathAtt_Lov(ifrom,ito, 
     +           sopath_Lov(ifrom,ito,timeindex,ipick))%node_number

	  valso= MUCPath_Lov_Array(ifrom,ito,
     +           sopath_Lov(ifrom,ito,timeindex,ipick))%P(ihh)
		

! skip the centroid of the connector, skip the upstream node of generation link

	  if(ihh.gt.2) then

		ih = ih +1
        Index1D = ih
	  call VhcAtt_Insert(j,Index1D,1,valso)
        endif   

       enddo
! End of modification

       nnpath(j) = ih 
	 call VhcAtt_Clear(j,ih+1)

       return
       end

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


       subroutine get_genelink_from_sopath_lov(j,igenelink)

       use muc_mod
	 use vector_mod

       integer j,igenelink,timeindex
       real uniform 
       

     

       timeindex = 0

       ifrom = jorigin(j)
       ito = MasterDest(jdest(j))
       timeindex = ifix((stime(j)/tii)/tad)+1 
       call DYNA_random_number(uniform,6)


       do np = 1, NumSopath_lov(ifrom,ito,timeindex)
        if(soaccuprob_lov(ifrom,ito,timeindex,np).ge.uniform) exit
       enddo
	 jipick(j) = np 

	
	isize= MucPathAtt_lov(ifrom,ito,
     +           sopath_Lov(ifrom,ito,timeindex,jipick(j)))%node_number

	  iupstreamnode= MUCPath_Lov_Array(ifrom,ito,
     +           sopath_Lov(ifrom,ito,timeindex,jipick(j)))%P(2)

	  idownstreamnode= MUCPath_Lov_Array(ifrom,ito,
     +           sopath_Lov(ifrom,ito,timeindex,jipick(j)))%P(3)


	  igenelink = GetFLinkFromNode(iupstreamnode,idownstreamnode)

       return
       end




