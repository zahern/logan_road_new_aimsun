      subroutine vehicle_trajectory(l)
! --
! -- This subroutine prints out the file fort.18, which contains a detailed
! -- statistics about each vehicle trajectory.
! --
! -- This subroutine is called from final_statistics (if the user selects
! -- to get the output file fort.18)
! -- This subroutine does not call any other subroutines.
! --
! -- INPUT : 
! -- all vehicle information via common blocks.
! --
! -- OUTPUT :
! --  fort.18 : vehicle trajectory for all vehicles.
! --  fort.188 : trajectories for buses.
! --
! -- GUI
! --   for GUI purpose, the following tag numbering scheme applies
! --       TAGGED    NON-TAGGED
! --   in     1          0
! --  out     2          3
! --  in this subroutine, only 1, 0 will apply
	use muc_mod
	use vector_mod
! --
! -- if notin of the vehicle =0, then the statistics for this vehicle
! -- has been printed out from get_veh_stat when it went out of the network.
! --
	write(18,*) '#############################################'
	write(18,*) '######Vehicles still in the network   #######'
	write(18,*) '#############################################'
	if(i18.gt.0) then
      do 1899 j=1,jj   

!      if(notin(j).eq.1) go to 1899
      	if(notin(j).eq.1.or.isec(j).eq.0) go to 1899

!      tmp1=l*tii-stime(j)
	   tmp1=ttilnow(j)

      if(tmp1.lt.0.0) tmp1=999.00
!     write(18,1890) j,itag(j), info(j),nodenum(iunod(isec(j))),nodenum(nint(VhcAtt_Value(j,1,1))),nodenum(nint(VhcAtt_Value(j,VhcAtt_Size(j)-1,1))),stime(j),tmp1,icurrnt(j),vehclass2(j)


	  if(itag(j).eq.0) then !for GUI purpose, if the itag = 0 write out as 3
       write(18,1890) j,0, jorigin(j), jdest(j),vehclass(j),
     + nodenum(iunod(isec(j))),nodenum(nint(VhcAtt_Value(j,1,1))),
     + nodenum(nint(VhcAtt_Value(j,VhcAtt_Size(j)-1,1))),
     + stime(j),tmp1,icurrnt(j),vehclass2(j),ioc(j)
	  else
       write(18,1890) j,itag(j),jorigin(j),jdest(j),vehclass(j),
     + nodenum(iunod(isec(j))),nodenum(nint(VhcAtt_Value(j,1,1)))
     + ,nodenum(nint(VhcAtt_Value(j,VhcAtt_Size(j)-1,1))),stime(j)
     + ,tmp1,icurrnt(j),vehclass2(j),ioc(j)
	  endif
      write(18,1891) (nodenum(nint(VhcAtt_Value(j,js,1))),
     + js=1,icurrnt(j))
      write(18,*)    '==>Node Exit Time Point'
      write(18,1892) (VhcAtt_Value(j,jn,3),jn=1,icurrnt(j)-1) ! pathtime don't print the value for the last node
      write(18,*)    '==>Link Travel Time'
      write(18,1892) (VhcAtt_Value(j,jn,4),jn=1,icurrnt(j)-1) ! timediff
      write(18,*)    '==>Accumulated Stop Time'
      write(18,1892) (VhcAtt_Value(j,jn,2),jn=1,icurrnt(j)-1) ! pathstop
      write(18,*)

1890  format('Veh #',i7,' Tag=',i2,' OrigZ=',i3,' DestZ=',i3,
     + ' Class=',i2,' UstmN=',i7,' DownN=',i7,' DestN=',i7,
     + ' STime=',f7.2,' Total Travel Time=',f7.2,' # of Nodes='
     + ,i4, ' VehType',i2,' LOO', i2)
c	1890  format('Veh #',i7,' Tag=',i2,' OrigZ=',i3,' DestZ=',i3,' class=',i2,' Ustm=',i,' OrigN=',i7,' DestN=',i7,' STime=',f7.2,' Total Travel Time=',f7.2,' # of Nodes=',i4, ' VehType',i2)
1891  format(10i7)
1892  format(10f7.2)

! -- Print bus information
! -- 

       do ibus=1,nubus
        if(busid(ibus).eq.j) then
          write(188,*) 'Statistics for bus number  ',ibus,distans(j)
          write(188,1890) j,itag(j),info(j),nodenum(iunod(isec(j)))
     + ,nodenum(nint(VhcAtt_Value(j,1,1))),nodenum(nint(VhcAtt_Value(
     + j,VhcAtt_Size(j)-1,1))),stime(j),tmp1,icurrnt(j),vehclass2(j)
          write(188,1891) (nodenum(nint(VhcAtt_Value(j,js,1))),js=1,
     +  icurrnt(j))
          write(188,*)    '==>Node Exit Time Point'
          write(188,1892) (VhcAtt_Value(j,jn,3),jn=1,icurrnt(j)-1)
          write(188,*)    '==>Link Travel Time'
          write(188,1892) (VhcAtt_Value(j,jn,4),jn=1,icurrnt(j)-1)
          write(188,*)    '==>Accumulated Stop Time'
          write(188,1892) (VhcAtt_Value(j,jn,2),jn=1,icurrnt(j)-1)
          write(188,*)
        endif
       enddo
       write(188,*)

 

1899   continue
	endif
	return
    	end
